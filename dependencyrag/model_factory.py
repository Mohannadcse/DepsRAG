"""
Shared model factory for DepsRAG.
Provides a single source of truth for creating LLM model instances.
"""

import os
from typing import Optional
from agno.models.openai import OpenAIChat
from agno.models.azure import AzureOpenAI
from agno.models.google import Gemini
from agno.models.base import Model


def create_model(model_id: str = "gpt-4o", provider: Optional[str] = None) -> Model:
    """
    Create appropriate LLM model based on provider or auto-detect from environment.

    Args:
        model_id: Model ID to use (default: gpt-4o)
        provider: Explicit provider ("openai", "azure", "google") or None for auto-detect

    Returns:
        Model: Configured model instance (OpenAIChat, AzureOpenAI, or Gemini)
    """
    # Explicit provider specified
    if provider == "google":
        # Use GOOGLE_MODEL_ID from env if model_id is default
        gemini_model = os.getenv("GOOGLE_MODEL_ID", "gemini-2.0-flash-exp") if model_id == "gpt-4o" else model_id
        return Gemini(id=gemini_model)
    elif provider == "azure":
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT") or os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME") or model_id
        return AzureOpenAI(
            id=model_id,
            azure_deployment=deployment,
        )
    elif provider == "openai":
        return OpenAIChat(id=model_id)

    # Auto-detect based on environment variables
    if os.getenv("AZURE_OPENAI_API_KEY"):
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT") or os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME") or model_id
        return AzureOpenAI(
            id=model_id,
            azure_deployment=deployment,
        )
    elif os.getenv("GOOGLE_API_KEY"):
        gemini_model = os.getenv("GOOGLE_MODEL_ID", "gemini-2.0-flash-exp") if model_id == "gpt-4o" else model_id
        return Gemini(id=gemini_model)

    # Default to OpenAI
    return OpenAIChat(id=model_id)
