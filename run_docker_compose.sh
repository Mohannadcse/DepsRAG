#!/bin/bash

# Prompt the user for the mode (cli or ui)
read -p "Enter the mode (cli/ui): " MODE

# Run the appropriate commands based on the user's input
if [ "$MODE" == "cli" ]; then
  echo "Starting in CLI mode..."
  docker compose up -d
  docker compose exec -e APP_MODE=cli depsrag-app bash -c '/app/entrypoint.sh'
elif [ "$MODE" == "ui" ]; then
  echo "Starting in UI mode..."
  docker compose up -d
  docker compose exec -e APP_MODE=ui depsrag-app bash -c '/app/entrypoint.sh'
else
  echo "Invalid mode. Please enter 'cli' or 'ui'."
fi
