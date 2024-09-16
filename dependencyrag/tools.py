import json
import requests
from typing import List

import langroid as lr
from langroid.utils.constants import NO_ANSWER

from langroid.pydantic_v1 import BaseModel, Field


class AnswerSteps(BaseModel):
    step_query: str = Field(..., description="The query for reference")
    step_evidence: str = Field(
        ..., description="Cypher Query or URL link for grounding"
    )
    step_answer: str = Field(..., description="Answer intermediate step")


class AskNewQuestionTool(lr.ToolMessage):
    request = "ask_new_question_tool"
    purpose = "Ask a new <question>"
    question: str


class AnswerTool(lr.ToolMessage):
    request = "answer_tool"
    purpose = "Present the <answer> to a question"
    answer: str


class AnswerToolGraphConstruction(lr.ToolMessage):
    """Wrapper for answer from construct_dependency_graph"""

    request = "answer_tool_graph"
    purpose = "Present the <answer> to a question"
    answer: str


class FinalAnswerTool(lr.ToolMessage):
    request: str = "final_answer_tool"
    purpose: str = """
        Present the intermediate <steps> and
        final <answer> to the user's original <query>.
        """
    steps: str
    answer: str


class FeedbackTool(lr.ToolMessage):
    request: str = "feedback_tool"
    purpose: str = """
    Provide <feedback> on the user's answer. If the answer is valid based on the
    reasoning steps, then the feedback MUST be EMPTY
    """
    feedback: str
    suggested_fix: str

    @classmethod
    def examples(cls) -> List["lr.ToolMessage"]:
        return [
            # just example
            cls(feedback="This looks fine!", suggested_fix=""),
            # thought + example
            (
                "I want to provide feedback on the reasoning steps and final answer",
                cls(
                    feedback="""
                    The answer is invalid because the conclusion does not follow from the
                    steps. Please check your reasoning and try again.
                    """,
                    suggested_fix="Check reasoning and try again",
                ),
            ),
        ]


class QuestionTool(lr.ToolMessage):
    request: str = "question_tool"
    purpose: str = """Ask a SINGLE <question> that can be answered. <target_agent>
    indicates the agent that should provide the answer.
    You should specify "DependencyGraphAgent" if the answer should be obtained from the
    graph database OR "RetrieverAgent" if the question asks about vulnerability or
    should be answered using web search.
    """
    question: str
    target_agent: str


class VulnerabilityCheck(lr.ToolMessage):
    request = "vulnerability_check"
    purpose = """
      Use this tool/function to check for vulnerabilities based on the provided
      <package_version>, <package_type>, and <package_name>.
      DO NOT make assumption about <package_type> and <package_name>, ask the user to
      provide them.
      """
    package_version: str
    package_type: str
    package_name: str

    def handle(self) -> str:
        if self.package_type.lower() == "pypi":
            ecosystem = "PyPI"
        # Data payload
        data = {
            "version": self.package_version,
            "package": {"name": self.package_name, "ecosystem": ecosystem},
        }

        # URL
        url = "https://api.osv.dev/v1/query"

        # Send POST request
        response = requests.post(url, data=json.dumps(data))
        response_data = response.json()
        if "vulns" in response_data:
            for vuln in response_data["vulns"]:
                if "references" in vuln:
                    del vuln["references"]
                if "affected" in vuln:
                    for affected in vuln["affected"]:
                        if "versions" in affected:
                            del affected["versions"]
        return f"""Here is the vulnerability Result:
        {json.dumps(response_data, indent=4)}"""


class ConstructDepsGraphTool(lr.ToolMessage):
    request = "construct_dependency_graph"
    purpose = f"""Get package <package_version>, <package_type>, and <package_name>.
    For the <package_version>, obtain the recent version, it should be a number.
    For the <package_type>, return if the package is PyPI, NPM, or Maven.
      Otherwise, return {NO_ANSWER}.
    For the <package_name>, return the package name provided by the user.
    ALL strings are in lower case.
    """
    package_version: str
    package_type: str
    package_name: str


class VisualizeGraph(lr.ToolMessage):
    request = "visualize_dependency_graph"
    purpose = """
      Use this tool/function to display the dependency graph.
      """
    package_version: str
    package_type: str
    package_name: str
    query: str
