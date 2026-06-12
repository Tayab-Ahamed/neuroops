import os
from typing import Any, TypeVar

import structlog
from pydantic import BaseModel

logger = structlog.get_logger()

T = TypeVar("T", bound=BaseModel)


def get_llm(structured_schema: type[T] | None = None, complexity_score: float = 0.5) -> Any:
    """Initializes and returns the configured LangChain LLM, optionally bound to a structured output schema."""
    provider = os.getenv("LLM_PROVIDER", "").lower()
    routing_enabled = os.getenv("MODEL_ROUTING_ENABLED", "true").lower() == "true"

    # Auto-detect if provider not explicitly set
    if not provider:
        if os.getenv("ANTHROPIC_API_KEY"):
            provider = "anthropic"
        elif os.getenv("OPENAI_API_KEY"):
            provider = "openai"
        else:
            # Check if we should fall back to Ollama or mock
            provider = (
                "ollama" if os.getenv("OLLAMA_MODEL") or os.getenv("OLLAMA_BASE_URL") else "mock"
            )

    llm = None

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        if routing_enabled:
            if complexity_score < 0.35:
                model_name = "claude-haiku-4-5-20251001"
                max_tokens = None
            elif complexity_score <= 0.70:
                model_name = "claude-sonnet-4-6"
                max_tokens = None
            else:
                model_name = "claude-sonnet-4-6"
                max_tokens = 4096
        else:
            model_name = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
            max_tokens = None

        logger.info(
            "Initializing Anthropic ChatAnthropic model via router",
            model=model_name,
            complexity_score=complexity_score,
            routing_enabled=routing_enabled,
        )
        kwargs = {
            "model": model_name,
            "temperature": 0,
            "extra_headers": {"anthropic-beta": "prompt-caching-2024-07-31"},
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        llm = ChatAnthropic(**kwargs)

    elif provider == "openai":
        from langchain_openai import ChatOpenAI

        model_name = os.getenv("OPENAI_MODEL", "gpt-4o")
        logger.info("Initializing OpenAI ChatOpenAI model", model=model_name)
        llm = ChatOpenAI(model=model_name, temperature=0)

    elif provider == "ollama":
        from langchain_openai import ChatOpenAI

        model_name = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        logger.info(
            "Initializing local Ollama model via ChatOpenAI compatibility",
            model=model_name,
            base_url=base_url,
        )
        # ChatOpenAI compatibility mode for Ollama
        llm = ChatOpenAI(api_key="ollama", base_url=base_url, model=model_name, temperature=0)

    else:
        # Mock mode or local unit test mock fallback
        logger.info("No active LLM providers. Returning None (will trigger mock behaviors).")
        return None

    if structured_schema and llm is not None:
        return llm.with_structured_output(structured_schema)

    return llm


def get_llm_model_name(complexity_score: float) -> str:
    """Returns the name of the LLM model that would be used based on provider and complexity score."""
    provider = os.getenv("LLM_PROVIDER", "").lower()
    routing_enabled = os.getenv("MODEL_ROUTING_ENABLED", "true").lower() == "true"

    if not provider:
        if os.getenv("ANTHROPIC_API_KEY"):
            provider = "anthropic"
        elif os.getenv("OPENAI_API_KEY"):
            provider = "openai"
        else:
            provider = "mock"

    if provider == "anthropic":
        if routing_enabled:
            if complexity_score < 0.35:
                return "claude-haiku-4-5-20251001"
            else:
                return "claude-sonnet-4-6"
        else:
            return os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
    elif provider == "openai":
        return os.getenv("OPENAI_MODEL", "gpt-4o")
    else:
        return "mock"
