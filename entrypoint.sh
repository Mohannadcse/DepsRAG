#!/bin/bash

echo DEPSRAG_MODE=$DEPSRAG_MODE

if [ "$DEPSRAG_MODE" = "cli" ]; then
  echo "Starting Dependency Chatbot in CLI mode..."
  python dependencyrag/dependency_chatbot.py
else
  echo "Starting Dependency Chatbot using Chainlit..."
  chainlit run dependencyrag/chainlit/chainlit_dependency_chatbot.py --host 0.0.0.0 --port 8501
fi
