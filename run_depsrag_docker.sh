#!/bin/bash

# Prompt the user for the mode (cli or ui)
read -p "Enter the mode (cli/ui): " MODE

# Run the appropriate commands based on the user's input
if [ "$MODE" == "cli" ] || [ "$MODE" == "ui" ]; then
  docker compose up -d
  docker compose exec -e DEPSRAG_MODE=$MODE depsrag-app bash -c '/app/entrypoint.sh'
else
  echo "Invalid mode. Please enter 'cli' or 'ui'."
fi
