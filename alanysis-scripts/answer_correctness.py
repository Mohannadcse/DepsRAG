import json
import pandas as pd
import matplotlib.pyplot as plt


# Function to extract correct answers from the JSON data
def extract_correct_answers(data):
    correct_answers = {}
    for question, content in data.items():
        correct_answers[question] = [
            iteration["correct"] for iteration in content["iterations"]
        ]
    return correct_answers


# Load JSON data from files
with open("experiment_without_critic.json", "r") as f:
    data_without_critic_json = json.load(f)

with open("experiment_with_critic.json", "r") as f:
    data_with_critic_json = json.load(f)

# Extract correct answers from the JSON files
data_without_critic = extract_correct_answers(data_without_critic_json)
data_with_critic = extract_correct_answers(data_with_critic_json)

# Convert data to DataFrames
df_without_critic = pd.DataFrame(data_without_critic)
df_with_critic = pd.DataFrame(data_with_critic)

# Calculate the percentage of correct answers for each question over all iterations
percent_correct_without_critic = df_without_critic.mean() * 100
percent_correct_with_critic = df_with_critic.mean() * 100

# Calculate success rate (total correct answers / total iterations)
total_iterations_without_critic = df_without_critic.count().sum()
total_correct_without_critic = df_without_critic.sum().sum()
print(total_iterations_without_critic)
print(total_correct_without_critic)
success_rate_without_critic = (total_correct_without_critic / total_iterations_without_critic) * 100

total_iterations_with_critic = df_with_critic.count().sum()
total_correct_with_critic = df_with_critic.sum().sum()
success_rate_with_critic = (total_correct_with_critic / total_iterations_with_critic) * 100

# Calculate percentage improvement in success rate
if success_rate_without_critic != 0:
    percentage_improvement = ((success_rate_with_critic - success_rate_without_critic) / success_rate_without_critic) * 100
else:
    percentage_improvement = float('inf')  # Handle division by zero

# Print success rates and percentage improvement
print(f"Success Rate Without Critic-Agent: {success_rate_without_critic:.2f}%")
print(f"Success Rate With Critic-Agent: {success_rate_with_critic:.2f}%")
print(f"Percentage Improvement in Success Rate: {percentage_improvement:.2f}%")

# Plotting the results as a histogram with grayscale bars and hatching patterns
plt.figure(figsize=(10, 6))

# Define the bar width and the positions for the bars
bar_width = 0.35
index = range(1, 4)

# Plot bars for each experiment with grayscale colors and hatching patterns
plt.bar(
    [i - bar_width / 2 for i in index],
    percent_correct_without_critic,
    width=bar_width,
    color="gray",
    label="Without Critic-Agent Interaction",
    hatch="//",
)
plt.bar(
    [i + bar_width / 2 for i in index],
    percent_correct_with_critic,
    width=bar_width,
    color="darkgray",
    label="With Critic-Agent Interaction",
    hatch="\\",
)

# plt.title('Percentage of Correct Answers Over All Iterations (With vs Without Critic Agent)')
# plt.xlabel('Questions')
plt.ylabel("Percentage of Correct Answers (%)", fontsize=18)
plt.xticks([1, 2, 3], ["T1", "T2", "T3"], fontsize=18)
plt.legend(fontsize=14)

# Set y-axis ticks and increase the font size
plt.yticks(fontsize=18)

# plt.grid(axis='y')
plt.grid(axis="y", linestyle="--", linewidth=0.7)

plt.tight_layout()

# Save the plot as a PDF before showing
plt.savefig("answer_correctness.pdf", format="pdf")

# Show the plot
plt.show()
