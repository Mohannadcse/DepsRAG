import logging

import langroid as lr
from langroid.agent.chat_agent import ChatAgent, ChatAgentConfig
from langroid.agent.tool_message import ToolMessage
from langroid.pydantic_v1 import BaseModel
from langroid.agent.chat_document import ChatDocument
from langroid.mytypes import Entity
from langroid.utils.constants import DONE, NO_ANSWER, PASS, PASS_TO
from langroid.agent.task import Task
from langroid.agent.special.neo4j.neo4j_chat_agent import Neo4jChatAgent

logger = logging.getLogger(__name__)


# Common stuff to be used by the agents #####
class QueryPlan(BaseModel):
    original_query: str
    query: str
    filter: str


class QueryPlanTool(ToolMessage):
    request = "query_plan"  # the agent method name that handles this tool
    purpose = """
    Given a user's query, generate a query <plan> consisting of:
    - <original_query> - the original query for reference
    - <filter> condition if needed (or empty string if no filter is needed)
    - <query> - a possibly rephrased query that can be used to match the CONTENT
        of the documents (can be same as <original_query> if no rephrasing is needed)
    """
    plan: QueryPlan


class QueryPlanAnswerTool(ToolMessage):
    request = "query_plan_answer"  # the agent method name that handles this tool
    purpose = """
    Assemble query <plan> and <answer>
    """
    plan: QueryPlan
    answer: str


class QueryPlanFeedbackTool(ToolMessage):
    request = "query_plan_feedback"
    purpose = """
    To give <feedback> regarding the query plan,
    along with a <suggested_fix> if any (empty string if no fix is suggested).
    """
    feedback: str
    suggested_fix: str


class KGQueryPlanAgentConfig(ChatAgentConfig):
    name: str = "KGPlanner"
    critic_name: str = "QueryPlanCritic"
    kg_agent_name: str = "Neo4jRAG"
    kg_schema: str = ""
    use_tools = False
    max_retries: int = 5  # max number of retries for query plan
    use_functions_api = True
    system_message: str = ""

    def set_system_message(self) -> None:
        self.system_message = self.system_message.format(
            kg_schema=self.kg_schema,
        )


# CriticAgent Stuff ########
class QueryPlanCriticConfig(KGQueryPlanAgentConfig):
    name: str = "QueryPlanCritic"
    system_message = f"""
    You are an expert at carefully planning a query that needs to be answered
    based on a graph database. This graph database has the SCHEMA below:

    {{kg_schema}}

    You will receive a QUERY PLAN consisting of:
    - ORIGINAL QUERY,
    - Cypher-Like FILTER, WHICH CAN BE EMPTY (and it's fine if results sound reasonable)
      FILTER SHOULD ONLY BE USED IF EXPLICITLY REQUIRED BY THE QUERY.
    - REPHRASED QUERY that will be used to match against the CONTENT (not filterable)
         of the graph database.

    Your job is to act as a CRITIC and provide feedback,
    ONLY using the `query_plan_feedback` tool, and DO NOT SAY ANYTHING ELSE.

    Here is how you must examine the QUERY PLAN + ANSWER:
    - ALL filtering conditions in the original query must be EXPLICITLY
      mentioned in the FILTER, and the QUERY field should not be used for filtering.
    - If the ANSWER contains an ERROR message, then this means that the query
      plan execution FAILED, and your feedback should say INVALID along
      with the ERROR message, `suggested_fix` that aims to help the assistant
      fix the problem (or simply equals "address the the error shown in feedback")
    - Ask yourself, is the ANSWER in the expected form, e.g.
        if the question is asking for the name of an ENTITY with max SIZE,
        then the answer should be the ENTITY name, NOT the SIZE!! 
    - If the ANSWER is in the expected form, then the QUERY PLAN is likely VALID,
      and your feedback should say VALID, with empty `suggested_fix`.
      ===> HOWEVER!!! Watch out for a spurious correct-looking answer, for EXAMPLE:
      the query was to find the ENTITY with a maximum SIZE, 
      but the dataframe calculation is find the SIZE, NOT the ENTITY!!      
    - If the ANSWER is {NO_ANSWER} or of the wrong form, 
      then try to DIAGNOSE the problem IN THE FOLLOWING ORDER:
      - If the REPHRASED QUERY looks correct, then check if the FILTER makes sense.
        REMEMBER: A filter should ONLY be used if EXPLICITLY REQUIRED BY THE QUERY.

    ALWAYS use `query_plan_feedback` tool/fn to present your feedback
    in the `feedback` field, and if any fix is suggested,
    present it in the `suggested_fix` field.
    DO NOT SAY ANYTHING ELSE OUTSIDE THE TOOL/FN.
    IF NO REVISION NEEDED, simply leave the `suggested_fix` field EMPTY,
    and SAY NOTHING ELSE
    and DO NOT EXPLAIN YOURSELF.
    """


def plain_text_query_plan(msg: QueryPlanAnswerTool) -> str:
    plan = f"""
    OriginalQuery: {msg.plan.original_query}
    Filter: {msg.plan.filter}
    Rephrased Query: {msg.plan.query}
    Answer: {msg.answer}
    """
    return plan


class QueryPlanCritic(ChatAgent):
    def __init__(self, cfg: KGQueryPlanAgentConfig):
        super().__init__(cfg)
        self.config = cfg
        self.enable_message(QueryPlanAnswerTool, use=False, handle=True)
        self.enable_message(QueryPlanFeedbackTool, use=True, handle=True)

    def query_plan_answer(self, msg: QueryPlanAnswerTool) -> str:
        """Present query plan + answer in plain text (not JSON)
        so LLM can give feedback"""
        return plain_text_query_plan(msg)

    def query_plan_feedback(self, msg: QueryPlanFeedbackTool) -> str:
        """Format Valid so return to Query Planner"""
        return DONE + " " + PASS  # return to Query Planner

    def handle_message_fallback(
        self, msg: str | ChatDocument
    ) -> str | ChatDocument | None:
        """Remind the LLM to use QueryPlanFeedbackTool since it forgot"""
        if isinstance(msg, ChatDocument) and msg.metadata.sender == Entity.LLM:
            return """
            You forgot to use the `query_plan_feedback` tool/function.
            Re-try your response using the `query_plan_feedback` tool/function,
            remember to provide feedback in the `feedback` field,
            and if any fix is suggested, provide it in the `suggested_fix` field.
            """
        return None


# PlanningAgent Stuff ########
class Neo4jQueryPlanAgent(ChatAgent):
    def __init__(self, config: KGQueryPlanAgentConfig):
        super().__init__(config)
        self.config: KGQueryPlanAgentConfig = config
        self.curr_query_plan: QueryPlan | None = None
        # how many times re-trying query plan in response to feedback:
        self.n_retries: int = 0
        self.result: str = ""  # answer received from Neo4jRAG
        # This agent should generate the QueryPlanTool
        # as well as handle it for validation
        self.enable_message(QueryPlanTool, use=True, handle=True)
        self.enable_message(QueryPlanFeedbackTool, use=False, handle=True)
        self.config.system_message = f"""
            You will receive a QUERY, to be answered based on an EXTREMELY LARGE collection
            of documents you DO NOT have access to, but your ASSISTANT does.
            You only know that these documents have a special `content` field
            and additional FILTERABLE fields in the SCHEMA below:

            {{doc_schema}}

            Based on the QUERY and the above SCHEMA, your task is to determine a QUERY PLAN,
            consisting of:
            -  a FILTER (can be empty string) that would help the ASSISTANT to answer the query.
                Remember the FILTER can refer to ANY fields in the above SCHEMA
                EXCEPT the `content` field of the documents.
                ONLY USE A FILTER IF EXPLICITLY MENTIONED IN THE QUERY.
                TO get good results, for STRING MATCHES, consider using LIKE instead of =, e.g.
                "CEO LIKE '%Jobs%'" instead of "CEO = 'Steve Jobs'"
            - a possibly REPHRASED QUERY to be answerable given the FILTER.
                Keep in mind that the ASSISTANT does NOT know anything about the FILTER fields,
                so the REPHRASED QUERY should NOT mention ANY FILTER fields.
                The assistant will answer based on documents whose CONTENTS match the QUERY, 
                possibly REPHRASED.

            Use `recipient_message` tool/function-call, where the `recipient` field is the name
            of the intended recipient to forward the message to `Neo4jRAG`.

            You must FIRST present the QUERY PLAN using the `query_plan` tool/function.
            This will be handled by your document assistant, who will produce an ANSWER.

            You may receive FEEDBACK on your QUERY PLAN and received ANSWER,
            from the 'QueryPlanCritic' who may offer suggestions for
            a better FILTER, REPHRASED QUERY.

            If you keep getting feedback or keep getting a {NO_ANSWER} from the assistant
            at least 3 times, then simply say '{DONE} {NO_ANSWER}' and nothing else.
            """

    def query_plan(self, msg: QueryPlanTool) -> str:
        """Valid, forward to RAG Agent"""
        # save, to be used to assemble QueryPlanResultTool
        self.curr_query_plan = msg.plan
        return PASS_TO + self.config.kg_agent_name

    def query_plan_feedback(self, msg: QueryPlanFeedbackTool) -> str:
        """Process Critic feedback on QueryPlan + Answer from RAG Agent"""
        # We should have saved answer in self.result by this time,
        # since this Agent seeks feedback only after receiving RAG answer.
        if msg.suggested_fix == "":
            self.n_retries = 0
            # This means the Query Plan or Result is good, as judged by Critic
            if self.result == "":
                # This was feedback for query with no result
                return "QUERY PLAN LOOKS GOOD!"
            elif self.result == NO_ANSWER:
                return NO_ANSWER
            else:  # non-empty and non-null answer
                return DONE + " " + self.result
        self.n_retries += 1
        if self.n_retries >= self.config.max_retries:
            # bail out to avoid infinite loop
            self.n_retries = 0
            return DONE + " " + NO_ANSWER
        return f"""
        here is FEEDBACK about your QUERY PLAN, and a SUGGESTED FIX.
        Modify the QUERY PLAN if needed:
        FEEDBACK: {msg.feedback}
        SUGGESTED FIX: {msg.suggested_fix}
        """

    def handle_message_fallback(
        self, msg: str | ChatDocument
    ) -> str | ChatDocument | None:
        """
        Process answer received from RAG Agent:
         Construct a QueryPlanAnswerTool with the answer,
         and forward to Critic for feedback.
        """
        # TODO we don't need to use this fallback method. instead we can
        # first call result = super().agent_response(), and if result is None,
        # then we know there was no tool, so we run below code
        if (
            isinstance(msg, ChatDocument)
            and self.curr_query_plan is not None
            and msg.metadata.parent is not None
        ):
            # save result, to be used in query_plan_feedback()
            self.result = msg.content
            # assemble QueryPlanAnswerTool...
            query_plan_answer_tool = QueryPlanAnswerTool(  # type: ignore
                plan=self.curr_query_plan,
                answer=self.result,
            )
            response_tmpl = self.create_agent_response()
            # ... add the QueryPlanAnswerTool to the response
            # (Notice how the Agent is directly sending a tool, not the LLM)
            response_tmpl.tool_messages = [query_plan_answer_tool]
            # set the recipient to the Critic so it can give feedback
            response_tmpl.metadata.recipient = self.config.critic_name
            self.curr_query_plan = None  # reset
            return response_tmpl
        if (
            isinstance(msg, ChatDocument)
            and not self.has_tool_message_attempt(msg)
            and msg.metadata.sender == lr.Entity.LLM
        ):
            # remind LLM to use the QueryPlanFeedbackTool
            return """
            You forgot to use the `query_plan` tool/function.
            Re-try your response using the `query_plan` tool/function.
            """
        return None


class Neo4jRAGTaskCreator:
    @staticmethod
    def new(
        agent: Neo4jChatAgent,
        interactive: bool = True,
    ) -> Task:
        """
        Add a Neo4jFilterAgent to the Neo4jChatAgent,
        set up the corresponding Tasks, connect them,
        and return the top-level query_plan_task.
        """
        kg_agent_name = "Neo4jRAG"
        critic_name = "QueryPlanCritic"
        query_plan_agent_config = KGQueryPlanAgentConfig(
            critic_name=critic_name,
            kg_agent_name=kg_agent_name,
            kg_schema=agent.get_schema(agent),
            llm=agent.config.llm,
        )
        query_plan_agent_config.set_system_message()

        critic_config = QueryPlanCriticConfig(
            kg_schema=agent.get_schema(agent), llm=agent.config.llm
        )
        critic_config.set_system_message()

        query_planner = Neo4jQueryPlanAgent(query_plan_agent_config)
        query_planner.enable_message(lr.agent.tools.RecipientTool)
        query_plan_task = Task(
            query_planner,
            interactive=interactive,
        )
        critic_agent = QueryPlanCritic(critic_config)
        critic_task = Task(
            critic_agent,
            interactive=False,
        )
        rag_task = Task(
            agent,
            name="Neo4jRAG",
            interactive=False,
            done_if_response=[Entity.LLM],  # done when non-null response from LLM
            done_if_no_response=[Entity.LLM],  # done when null response from LLM
        )
        query_plan_task.add_sub_task([critic_task, rag_task])
        return query_plan_task
