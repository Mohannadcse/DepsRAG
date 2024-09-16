from typing import Optional

import langroid as lr
from langroid import ChatDocument
from langroid.agent.tools.duckduckgo_search_tool import DuckduckgoSearchTool
from langroid.agent.tools.orchestration import (
    AgentDoneTool,
)
from dependencyrag.tools import (
    VulnerabilityCheck,
    QuestionTool,
    AnswerTool,
)


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
