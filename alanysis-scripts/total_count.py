import json
import matplotlib.pyplot as plt
import numpy as np

# Load the JSON data for the experiment with the critic agent
with open("experiment_with_critic.json", "r") as f:
    data_with_critic = json.load(f)


# Function to extract the total number of terminations, questions asked, and critic corrections
def get_totals(data):
    total_terminations = {}
    total_questions_asked = {}
    total_critic_corrections = {}

    for question_id, question_data in data.items():
        terminations = sum(
            iteration["termination"] for iteration in question_data["iterations"]
        )
        questions_asked = sum(
            iteration["num_questions_asked"]
            for iteration in question_data["iterations"]
        )
        critic_corrections = sum(
            iteration["num_corrected_agent_responses"]
            for iteration in question_data["iterations"]
        )

        total_terminations[question_id] = terminations
        total_questions_asked[question_id] = questions_asked
        total_critic_corrections[question_id] = critic_corrections

    return total_terminations, total_questions_asked, total_critic_corrections


# Get totals for terminations, questions asked, and critic corrections
total_terminations, total_questions_asked, total_critic_corrections = get_totals(
    data_with_critic
)


# Visualization: Grouped bar chart for terminations, questions asked, and critic corrections
def plot_totals(terminations, questions_asked, critic_corrections, output_file):
    question_ids = list(terminations.keys())
    num_questions = np.arange(len(question_ids))

    # Data for the bar chart
    terminations_values = list(terminations.values())
    questions_asked_values = list(questions_asked.values())
    critic_corrections_values = list(critic_corrections.values())

    bar_width = 0.25  # Width of the bars

    # Create the figure
    plt.figure(figsize=(10, 6))

    # Bar positions for each group
    r1 = np.arange(len(question_ids))
    r2 = [x + bar_width for x in r1]
    r3 = [x + bar_width for x in r2]

    # Plotting the bars with distinguishable hatches
    plt.bar(
        r1,
        terminations_values,
        color="lightgray",
        width=bar_width,
        edgecolor="black",
        hatch="/",
        label="Critic-Agent Termination",
    )
    plt.bar(
        r2,
        questions_asked_values,
        color="darkgray",
        width=bar_width,
        edgecolor="black",
        hatch="\\",
        label="Questions Asked by AssistantAgent",
    )
    plt.bar(
        r3,
        critic_corrections_values,
        color="black",
        width=bar_width,
        edgecolor="black",
        hatch="x",
        label="Critic Correction Requests",
    )

    # Add labels without xlabel, only showing "Question <number>" in xticks
    question_labels = [f"T{i}" for i in question_ids]
    plt.xticks(
        [r + bar_width for r in range(len(question_ids))], question_labels, fontsize=18
    )

    plt.ylabel("Total Count over 10 iterations", fontsize=18)
    # Set y-axis ticks and increase the font size
    plt.yticks(fontsize=18)

    # Add horizontal grid lines
    plt.grid(axis="y", linestyle="--", linewidth=0.7)

    # Add a legend
    plt.legend(fontsize=14)

    # Save the plot as a PDF
    plt.tight_layout()
    plt.savefig(output_file, format="pdf")
    plt.show()


# Call the function to plot and save as PDF (without a title)
plot_totals(
    total_terminations,
    total_questions_asked,
    total_critic_corrections,
    "total_count_with_critic.pdf",
)
