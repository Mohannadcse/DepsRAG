#!/bin/bash

echo APP_MODE=$APP_MODE

if [ "$APP_MODE" = "cli" ]; then
  echo "Starting Dependency Chatbot in CLI mode..."
  python dependencyrag/dependency_chatbot.py
else
  echo "Starting Dependency Chatbot using Chainlit..."
  chainlit run dependencyrag/chainlit/chainlit_dependency_chatbot.py --host 0.0.0.0 --port 8501
fi
