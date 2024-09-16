from typing import Optional

import langroid as lr
from langroid import ChatDocument
from langroid.utils.constants import AT
from langroid.agent.tools.orchestration import (
    ForwardTool,
)

from dependencyrag.tools import (
    QuestionTool,
    AnswerTool,
    AskNewQuestionTool,
    AnswerToolGraphConstruction,
    FinalAnswerTool,
    FeedbackTool,
)


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

        # Following attributes are for analytical purposes
        self.final_answer: str = ""
        self.num_critic_responses: int = 0
        self.num_questions_asked: int = 0
        self.terminated = False

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
        self.num_questions_asked += 1
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
        - present your FINAL answer to the user's ORIGINAL QUERY and INCLUDE the
         provided query if AVAILABLE. OR
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
        self.final_answer = msg.answer
        # fwd to critic
        # return "DONE"
        return ForwardTool(agent="Critic")

    def ask_new_question_tool(self, msg: AskNewQuestionTool) -> str:
        msg = super().user_response("Please ask your question")
        self.accept_new_question = False
        self.original_query = None
        return msg

    def feedback_tool(self, msg: FeedbackTool) -> str:
        if msg.suggested_fix == "":
            self.original_query = None
            self.accept_new_question = True
            self.expecting_question_tool = False
            return "No more suggestions, DONE."
        else:
            if self.num_critic_responses > 9:
                self.terminated = True
                return "No more suggestions, DONE."
            self.num_critic_responses += 1
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
