"""
This script contains logic to collect some stats
while running DepsRAG.
"""

import json
import os

from dependencyrag.dependency_agent import DependencyGraphAgent
from dependencyrag.critic_agent import CriticAgent
from dependencyrag.assistant_agent import AssistantAgent
from dependencyrag.search_agent import SearchAgent


class IterationReport:
    def __init__(
        self,
        question_no: int,
        question_str: str,
        iteration_no: int,
        num_corrected_cypher_queries: int,
        num_corrected_agent_responses: int,
        num_questions_asked: int,
        answer: str,
        termination: bool,
    ):
        self.question_no = question_no
        self.question_str = question_str
        self.iteration_no = iteration_no
        self.num_corrected_cypher_queries = num_corrected_cypher_queries
        self.num_corrected_agent_responses = num_corrected_agent_responses
        self.num_questions_asked = num_questions_asked
        self.termination = termination
        self.answer = answer

    def to_dict(self):
        # Return a dictionary of the iteration details
        return {
            "iterationNo": self.iteration_no,
            "num_corrected_cypher_queries": self.num_corrected_cypher_queries,
            "num_corrected_agent_responses": self.num_corrected_agent_responses,
            "num_questions_asked": self.num_questions_asked,
            "Answer": self.answer,
            "termination": self.termination,
        }

    def __repr__(self):
        return (
            f"IterationReport(question_no={self.question_no}, iteration_no={self.iteration_no}, "
            f"num_corrected_cypher_queries={self.num_corrected_cypher_queries}, "
            f"num_corrected_agent_responses={self.num_corrected_agent_responses}, "
            f"num_questions_asked={self.num_questions_asked}, "
            f"answer='{self.answer}')"
            f"termination='{self.termination}')"
        )


# Function to append to JSON file with question_no and question_str
def append_to_json_file(report, filename="iteration_report.json"):
    # Check if the file exists
    if os.path.exists(filename):
        # Read existing data
        with open(filename, "r") as file:
            try:
                data = json.load(file)
            except json.JSONDecodeError:
                data = {}  # If the file is empty or invalid, start with an empty dict
    else:
        data = {}

    # Ensure that the question_no key holds both the question and a list of iterations
    if str(report.question_no) not in data:
        # If the question_no does not exist, create a new dictionary for it
        data[str(report.question_no)] = {
            "question": report.question_str,
            "iterations": [],
        }
    elif not isinstance(data[str(report.question_no)]["iterations"], list):
        # If the value for iterations is not a list, convert it to a list (fixing invalid data)
        data[str(report.question_no)]["iterations"] = [
            data[str(report.question_no)]["iterations"]
        ]

    # Append the new iteration report to the list of iterations
    data[str(report.question_no)]["iterations"].append(report.to_dict())

    # Write the updated dictionary back to the file
    with open(filename, "w") as file:
        json.dump(data, file, indent=4)


def store_and_reset_analytics_attributes(
    iteration: int,
    dep_agent: DependencyGraphAgent,
    asst_agent: AssistantAgent,
    critic_agent: CriticAgent,
    retriever_agent: SearchAgent,
    question_no: int,
    question_str: str,
):
    append_to_json_file(
        IterationReport(
            question_no,
            question_str,
            iteration,
            dep_agent.num_corrected_cypher_queries,
            asst_agent.num_critic_responses,
            asst_agent.num_questions_asked,
            asst_agent.final_answer,
            asst_agent.terminated,
        )
    )

    dep_agent.num_corrected_cypher_queries = 0
    asst_agent.num_critic_responses = 0
    asst_agent.num_questions_asked = 0
    asst_agent.terminated = False
    asst_agent.final_answer = ""
    # clear history for all agents
    critic_agent.clear_history(0)
    dep_agent.clear_history(0)
    asst_agent.clear_history(0)
    retriever_agent.clear_history(0)
