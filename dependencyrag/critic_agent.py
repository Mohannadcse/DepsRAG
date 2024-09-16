import langroid as lr
from langroid import ChatDocument
from langroid.agent.tools.orchestration import (
    AgentDoneTool,
)

from dependencyrag.tools import FinalAnswerTool, FeedbackTool


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
