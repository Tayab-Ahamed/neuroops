import os
from typing import Any, TypeVar

import structlog
from pydantic import BaseModel

logger = structlog.get_logger()

T = TypeVar("T", bound=BaseModel)


def get_llm(structured_schema: type[T] | None = None) -> Any:
    """Initializes and returns the configured LangChain LLM, optionally bound to a structured output schema."""
    provider = os.getenv("LLM_PROVIDER", "").lower()

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

        model_name = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
        logger.info("Initializing Anthropic ChatAnthropic model", model=model_name)
        # Enable prompt caching via beta header
        llm = ChatAnthropic(
            model=model_name,
            temperature=0,
            extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"},
        )

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
