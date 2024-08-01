# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Install Poetry
RUN pip install poetry

# Set environment variables to prevent poetry from creating a virtual environment
ENV POETRY_VIRTUALENVS_CREATE=false

# Set the working directory in the container
WORKDIR /app

# Copy only the dependency files first to leverage Docker cache
COPY pyproject.toml poetry.lock /app/

# Install the dependencies
RUN poetry install

# Copy the rest of the application code
COPY . /app

# Copy the entrypoint script
COPY entrypoint.sh /app/

# Make the entrypoint script executable
RUN chmod +x /app/entrypoint.sh

# Set PYTHONPATH
ENV PYTHONPATH=/app

# Define environment variables
ENV NAME=DepsRAG \
    APP_MODE=cli

# Expose the ports for HTTP server
EXPOSE 8501
EXPOSE 5000

# Use the entrypoint script
ENTRYPOINT ["tail", "-f", "/dev/null"]
