"""Lazy Gemini/LangChain agent factory."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


class LangChainAgentFactory:
    """Create the standard model/tool loop through LangChain's public API."""

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        temperature: float = 1.0,
        system_prompt: str = "",
    ) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self.temperature = temperature
        self.system_prompt = system_prompt

    def create(self, tools: Sequence[Any]) -> Any:
        try:
            from langchain.agents import create_agent
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError as exc:  # pragma: no cover - optional provider boundary
            raise RuntimeError(
                "LangChain Gemini support requires langchain, langchain-core, "
                "and langchain-google-genai."
            ) from exc

        model = ChatGoogleGenerativeAI(
            model=self.model_name,
            google_api_key=self.api_key,
            temperature=self.temperature,
        )
        return create_agent(
            model=model,
            tools=list(tools),
            system_prompt=self.system_prompt or None,
        )
